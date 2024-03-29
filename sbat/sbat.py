"""
This is the central Module which is a class from which the different functions are called
"""

import logging
from pathlib import Path
import sys
import yaml

import numpy as np
import geopandas as gpd
import pandas as pd
import rasterio
from shapely import Point
from postprocess.plot import Plotter
from bflow.bflow import compute_baseflow, add_gauge_stats
from recession.recession import analyse_recession_curves
from recession.aquifer_parameter import get_hydrogeo_properties
from waterbalance.waterbalance import get_section_waterbalance, map_time_dependent_cols_to_gdf, uncertainty_data_generation

logger = logging.getLogger('sbat')
logger.setLevel(logging.INFO)

# define the logging output
Path(f'{Path(__file__).parents[1]}', 'output').mkdir(parents=True, exist_ok=True)
fh = logging.FileHandler(f'{Path(__file__).parents[1]}/output/sbat.log', mode='w')
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
fh.setFormatter(formatter)
logger.addHandler(fh)

class Model:
    def __init__(self, conf: dict, output: bool = True):
        """Initialization method for a new Model instance. Reads configuration, builds the working directory and reads
        the input data.

        Args:
            conf: Dictionary that contains the configurations from sbat.yaml
        """

        self.config = conf
        self.paths: dict = {"root": Path(__file__).parents[1]}
        self.output = output
        if not self.output:
            logging.info(f'Set output to {self.output} results in no plotting')
            self.config['file_io']['output']['plot_results'] = False

        self.gauge_ts = None
        self.gauges_meta = None

        self.bf_output = dict()
        self.recession_limbs_ts = None
        self.section_basin_map = None
        self.sections_meta = None
        self.q_diff = None
        self.network_map = None
        self.master_recession_curves = None

        self._build_wd()
        self._read_data()

    @staticmethod
    def read_config(config_file_path : Path
             ) -> dict:
        """Creates a dictionary out of a YAML file."""
        with open(config_file_path) as c:
            conf = yaml.safe_load(c)
        return conf

    def _build_wd(self):
        """Builds the working directory. Reads paths from configuration files and creates output directories."""

        self.paths["input_dir"] = Path(self.paths["root"],
                                       self.config['file_io']['input']['data_dir'])

        self.paths["output_dir"] = Path(self.paths["root"],
                                        self.config['file_io']['output']['output_directory'],
                                        self.config['info']['model_name'])
        if self.output:
            self.paths["output_dir"].mkdir(parents=True, exist_ok=True)
            Path(self.paths["output_dir"], 'data').mkdir(parents=True, exist_ok=True)

        self.paths["gauge_ts_path"] = Path(self.paths["input_dir"],
                                           self.config['file_io']['input']['gauges']['gauge_time_series'])
        self.paths["gauge_meta_path"] = Path(self.paths["input_dir"],
                                             self.config['file_io']['input']['gauges']['gauge_meta'])

    def _read_data(self):
        self.gauge_ts = pd.read_csv(self.paths["gauge_ts_path"], index_col=0, parse_dates=True)
        # all columns to lower case
        self.gauge_ts.columns = list(map(lambda x:x.lower(),self.gauge_ts.columns))
        # Slice gauge time series for start and end date
        self.gauge_ts = self.gauge_ts.loc[self.config['time']['start_date']:self.config['time']['end_date']]

        # we are only interested in metadata for which we have time series information; remove all nans
        self.gauge_ts = self.gauge_ts.dropna(axis=1, how='all')

        # log non-standard configuration
        if self.config['data_cleaning']['drop_na_axis'] is None:
            logger.info('No Nan Values are removed from time series data prior to computation')

        # todo: I do not really get what the following elifs do. Does the order of the axes make a difference? If no we
        #  we can drop over both axes by passing a tuple `axis=(0, 1)`. More important, NaNs are dropped over axis 1 by
        #  default (see some lines above)
        elif self.config['data_cleaning']['drop_na_axis'] == 1:
            logger.info('Remove Gauges which contain a nan entry')
            self.gauge_ts.dropna(axis=1, how='any').dropna(axis=0, how='any')
        elif self.config['data_cleaning']['drop_na_axis'] == 0:
            logging.info('Remove time steps which contain a nan entry')
            self.gauge_ts.dropna(axis=0, how='any').dropna(axis=1, how='any')

        try:
            self.gauge_ts.iloc[0]
        except IndexError:
            logger.exception('No data left after drop NA Values, consider to define dropna_axis as None or changing '
                             'start date and end_date')


        self.gauges_meta = pd.read_csv(self.paths["gauge_meta_path"], index_col=0)        
        #meta data also to lower case
        self.gauges_meta.index = list(map(lambda x:x.lower(),self.gauges_meta.index))
        self.gauges_meta.index.name = 'gauge'
        if self.config['data_cleaning']['valid_datapairs_only']:
            # reduce the metadata to the gauges for which we have actual time data
            intersecting_gauges = list(set(self.gauge_ts.columns).intersection(self.gauges_meta.index))
            
            self.gauges_meta = self.gauges_meta.loc[intersecting_gauges]
            # reduce the datasets to all which have metadata
            self.gauge_ts = self.gauge_ts[intersecting_gauges]

            logger.info(f'{self.gauge_ts.shape[1]} gauges with valid meta data')
            
        #we add a new column called decade
        
        # if we want to compute for each decade we do this here

        if self.config['time']['compute_each_decade']:
            no_of_gauges = len(self.gauges_meta)
            logger.info('Statistics for each gauge will be computed for each decade')
            start_decade = self.config['time']['start_date'].strftime('%Y')[0:3] + '5'
            end_decade = self.config['time']['end_date'].strftime('%Y')[0:3] + '5'
            decades = list(map(str,range(int(start_decade),int(end_decade)+1,10)))
            
            #extend dataset
            self.gauges_meta = pd.concat([self.gauges_meta]*len(decades))
            self.gauges_meta.loc[:,'decade'] = no_of_gauges * decades
            
        else:
            logger.info('Statistics for each gauge will be computed over the entire time series')
            self.gauges_meta.loc[:,'decade']=-9999



    #new baseflow function
    def get_baseflow(self,data_ts=pd.DataFrame(),data_var = 'Q*'):
        """
        

        Parameters
        ----------
        data_ts : TYPE, optional
            DESCRIPTION. The default is pd.DataFrame().

        Returns
        -------
        None.

        """
        # first we melt the time series to long version
        if 'gauge' not in data_ts.columns:
            data_ts=pd.melt(data_ts,ignore_index=False,value_name='Q*',var_name='gauge')
    
        #first we check whether data_ts has a column sample id
        if 'sample_id' not in data_ts.columns:
            data_ts['sample_id'] = 0
        
        data_ts_monthly=data_ts.groupby(['gauge','sample_id']).resample('m').mean(numeric_only=True).drop(columns='sample_id')
        bf_daily = pd.DataFrame()
        bf_monthly = pd.DataFrame()
        bfi_monthly = pd.DataFrame()
        
        bf_metrics_cols=['kge_'+col for col in self.config['baseflow']['methods']]
        
        # we further need the monthly averaged time series
 
        for (sample_id, gauge_name), subset in data_ts.groupby(['sample_id', 'gauge']):
            gauge_ts = subset[data_var].rename(gauge_name)
    
            bf_daily_ss, bf_monthly_ss, bfi_monthly_ss, performance_metrics_ss = compute_baseflow(
                                                gauge_ts,
                                                basin_area = self.gauges_meta.loc[gauge_name,'basin_area'],
                                                methods=self.config['baseflow']['methods'],
                                                compute_bfi=self.config['baseflow']['compute_baseflow_index']
                                                )
            #manipulate performance metrics
            performance_metrics_ss.update({'sample_id':sample_id,'gauge':gauge_name})
            performance_metrics=pd.DataFrame(performance_metrics_ss,index=[0])
            
            
            bf_daily_ss['sample_id'] = sample_id
            bf_daily_ss['gauge'] = gauge_name
            bf_daily_ss = pd.merge(bf_daily_ss.reset_index(),performance_metrics,on=['gauge','sample_id'],how='left')
            
            bf_monthly_ss['sample_id'] = sample_id
            bf_monthly_ss['gauge'] = gauge_name
            
            bfi_monthly_ss['sample_id'] = sample_id
            bfi_monthly_ss['gauge'] = gauge_name
            
            # Add to main
            bf_daily = pd.concat([bf_daily, bf_daily_ss])
            bf_monthly = pd.concat([bf_monthly, bf_monthly_ss.reset_index()])
            bfi_monthly = pd.concat([bfi_monthly, bfi_monthly_ss.reset_index()])

        # Add the prior information to the output data
        bf_daily = pd.merge(bf_daily, data_ts, on=['date', 'gauge', 'sample_id'], how='left').reset_index(drop=True)
        bf_monthly = pd.merge(bf_monthly, data_ts_monthly, on=['date', 'gauge', 'sample_id'], how='left').reset_index(drop=True)
        
        # Add results to class instance
        self.bf_output.update({'bf_daily': bf_daily, 
                               'bf_monthly': bf_monthly, 
                               'bfi_monthly': bfi_monthly})
        
        
        if self.config['baseflow']['compute_statistics']:
            logger.info('Compute baseflow statistics')
            logger.info('We calculate the mean over all methods and sample_ids')

            #add KGE data
            col_names={'bf_daily': 'BF', 
            'bf_monthly': 'BF', 
            'bfi_monthly': 'BFI'}
            for bf_type,bf_data in self.bf_output.items():
                #mean over method and sample_id
                bf_data_av = bf_data.groupby(['date','gauge']).mean(numeric_only=True)
                # pivot time series
                bf_data_pv = bf_data_av.reset_index().pivot(index='date',columns='gauge',values=col_names[bf_type])
                self.gauges_meta = self.gauges_meta.apply(lambda x:add_gauge_stats(x,bf_data_pv,
                                                                    col_name=bf_type,
                                                                    ),axis=1)
                
                if bf_type=='bf_daily':
                    #we add the KGE data
                    mean_cols = {k: f'{v}_mean' for k, v in zip(bf_metrics_cols, bf_metrics_cols)}
                    mean_stats = bf_data.groupby('gauge')[bf_metrics_cols].mean().rename(columns=mean_cols)
                    std_cols = {k: f'{v}_std' for k, v in zip(bf_metrics_cols, bf_metrics_cols)}
                    std_stats = bf_data.groupby('gauge')[bf_metrics_cols].std().rename(columns=std_cols)                    
                    mean_stats_extend = pd.concat([mean_stats]*int(len(self.gauges_meta)/len(mean_stats)))
                    std_stats_extend = pd.concat([std_stats]*int(len(self.gauges_meta)/len(std_stats)))
                    self.gauges_meta=pd.concat([self.gauges_meta.reset_index(),mean_stats_extend.reset_index(drop=True)],axis=1)
                    self.gauges_meta=pd.concat([self.gauges_meta,std_stats_extend.reset_index(drop=True)],axis=1)
                    
                    self.gauges_meta=self.gauges_meta.set_index('gauge')
                

        
        if self.output:
            #the meta data
            self.gauges_meta.to_csv(Path(self.paths["output_dir"], 'data', 'gauges_meta.csv'))
            for key in self.bf_output.keys():
                self.bf_output[key].to_csv(Path(self.paths["output_dir"], 'data',key+'.csv'))



    # %%function that adds discharge statistics

    def get_discharge_stats(self):
        """
        Calculates the daily and monthly discharge statistics for each gauge in the dataset.
        """

        #the daily discharge statistics
        self.gauges_meta = self.gauges_meta.apply(lambda x:add_gauge_stats(x,self.gauge_ts,
                                                            col_name=self.config['discharge']['col_name'],
                                                            ),axis=1)
        
        
        # if we want the monthly stats as well
        if self.config['discharge']['compute_monthly']:
            col_name = 'q_monthly'
            data = self.gauge_ts.copy(deep=True).resample('M').mean()        
            self.gauges_meta = self.gauges_meta.apply(lambda x:add_gauge_stats(x,data,
                                                                        col_name=col_name,
                                                                        ),axis=1)
        if self.output:
        #the meta data
            self.gauges_meta.to_csv(Path(self.paths["output_dir"], 'data', 'gauges_meta.csv'))
            

            
            
    # %%the function to call the resession curves
    def get_recession_curve(self):
        """Compute the recession curve for each gauge and decade."""

        logger.info('Started Recession Curve Analysis')

        # first we check whether we want to compute the recession of the water balance or of the hydrograph
        if self.config['recession']['curve_data']['curve_type'] == 'hydrograph':
            logger.info('Recession Analysis is conducted using the hydrograph data')

            # first we check whether baseflow data exist
            if self.config['recession']['curve_data']['flow_type'] == 'baseflow':
                if not self.bf_output:
                    logger.info('Calculate Baseflow first before baseflow water balance can be calculated')
                    self.get_baseflow()
                #convert data
                Q = self.bf_output['bf_daily']
                logger.info('we average the baseflow methods ')
                Q = Q.reset_index().groupby(['date', 'gauge']).mean(numeric_only=True).reset_index()
                # wide to long
                Q = Q.pivot(index='date', columns='gauge', values='BF').copy()

            elif self.config['recession']['curve_data']['flow_type'] == 'discharge':
                Q = self.gauge_ts


        elif self.config['recession']['curve_data']['curve_type'] == 'waterbalance':

            logger.warning('Recession Analysis is conducted using the waterbalance data, which is experimental')
            # in the case of waterbalance we can not compute a master recession curve due to possibly negative values
            logger.warning('mrc_curve not defined for curve_type is waterbalance')
            self.config['recession']['fitting']['mastercurve_algorithm'] = None
            # checking whether the water_balance exist and if the same flow type has been used
            if not hasattr(self, 'sections_meta') or not self.config['recession']['curve_data']['flow_type'] == \
                                                         self.config['waterbalance']['flowtype']:
                logger.info('Water_Balance Model is run first in order to get the correct input data for recession')
                self.get_water_balance(flow_type=self.config['recession']['curve_data']['flow_type'])

                Q = self.sections_meta.pivot(columns='downstream_point', values='balance', index='Date')
                Q.index = pd.to_datetime(Q.index).rename('date')
                Q.columns.name = 'gauge'

        if self.config['time']['compute_each_decade']:
            Q['decade'] = [x[0:3] + '5' for x in Q.index.strftime('%Y')]
        else:
            Q['decade'] = -9999

        # start the recession
        metrics = list()
        recession_limbs = list()
        Q_mrcs = list()
        for decade, Q_decade in Q.groupby('decade'):
            # drop all gauges where no data is within the decade
            Q_decade = Q_decade.dropna(axis=1, how='all').drop(columns='decade')
            # we loop trough all gauges to get the recession curve
            for gauge in Q_decade.columns:
                logger.info(f'compute recession curves for gauge {gauge} within decade {decade}')
                Q_rc, Q_mrc, mrc_out = analyse_recession_curves(Q_decade[gauge],
                                mrc_algorithm=
                                self.config['recession']['fitting'][
                                    'mastercurve_algorithm'],
                                recession_algorithm=
                                self.config['recession']['fitting'][
                                    'recession_algorithm'],
                                smooth_window_size=
                                self.config['recession'][
                                    'curve_data'][
                                    'moving_average_filter_steps'],
                                minimum_recession_curve_length=
                                self.config['recession']['curve_data'][
                                    'minimum_recession_curve_length'],
                                maximum_reservoirs=
                                self.config['recession']['fitting'][
                                    'maximum_reservoirs'],
                                minimum_limbs=
                                self.config['recession']['curve_data'][
                                    'minimum_limbs'],
                                inflection_split=
                                self.config['recession'][
                                    'curve_data'][
                                    'split_at_inflection'],
                                )
                # if data is None we just continue
                if Q_rc is None:
                    logger.warning(f'No Recession curves computable for gauge {gauge} within decade {decade}')
                    continue
                                        
                # we will add data to the metric
                metric = pd.DataFrame(np.expand_dims(mrc_out,0),
                                      columns=['rec_Q0', 'rec_n', 'pearson_r'],
                                      index=[0]
                                      )
                metric['decade'] = decade
                metric['gauge'] = gauge
                metric = metric.reset_index(drop=True).set_index(['gauge', 'decade'])
                metrics.append(metric)
                
                # we will add data to the recession limbs
                Q_rc['gauge'] = gauge
                Q_rc['decade'] = decade
                Q_rc['mrc_algorithm'] = self.config['recession']['fitting']['mastercurve_algorithm']
                Q_rc['flow_type'] = self.config['recession']['curve_data']['flow_type']
                Q_rc['curve_type'] = self.config['recession']['curve_data']['curve_type']
                Q_rc['recession_algorithm'] = self.config['recession']['fitting']['recession_algorithm']

                recession_limbs.append(Q_rc)        

                # convert master recession array to data Series
                Q_mrc=Q_mrc.to_frame()
                Q_mrc['section_time'] = Q_mrc.index.values
                Q_mrc['gauge'] = gauge
                Q_mrc['decade'] = decade
                
                Q_mrcs.append(Q_mrc)
                

       #concatenating the data and transfriiing                                 

        self.recession_limbs_ts = pd.concat(recession_limbs, axis=0, sort=False).reset_index(drop = True)

        self.master_recession_curves = pd.concat(Q_mrcs, axis=0).reset_index(drop = True)

        # append the metrics data to the metadata
        self.gauges_meta.index.name = 'gauge'
        df_metrics = pd.concat(metrics, axis=0)        
        self.gauges_meta = pd.merge(self.gauges_meta.reset_index(), 
                                     df_metrics.reset_index(),
                                     how='left',
                                     on=['gauge','decade'])
        #rearrange the gauge_meta
        self.gauges_meta = self.gauges_meta.reset_index(drop=True).set_index('gauge')
        
        #save the recession time series
        self.recession_ts = Q.copy()
        

        logger.info('Recession Curve Analysis Finished')

        # %%we infer the hydrogeological parameters if needed
        if self.config['recession']['hydrogeo_parameter_estimation']['activate']:
            # decide which kind of basins we need
            if self.config['recession']['curve_data']['curve_type'] == 'waterbalance':
                basins = self.section_basins
            elif self.config['recession']['curve_data']['curve_type'] == 'hydrograph':
                basins = gpd.read_file(Path(self.paths["input_dir"],
                                            self.config['file_io']['input']['geospatial']['gauge_basins'])
                                       )
                
                basins[self.config['waterbalance']['basin_id_col']] = basins[self.config['waterbalance']['basin_id_col']].apply(lambda x: x.lower())
                
                # we reduce the basins to the gauges for which we have meta information
                basins = basins.loc[basins[self.config['waterbalance']['basin_id_col']].isin(self.gauges_meta.index)]
            else:
                raise ValueError('curve type can either be waterbalance or hydrograph')
            # load the rasterio data
            try:
                gw_surface = rasterio.open(Path(self.paths["input_dir"],
                                                self.config['file_io']['input']['hydrogeology']['gw_levels']
                                                )
                                           )
            except Exception as e:
                logger.warning(e)
                logger.warning('As no gw data is provided, we try to enforce the simplify rorabaugh parameter estimation method')
                gw_surface = None
                
                self.config['recession']['hydrogeo_parameter_estimation']['rorabaugh_simplification'] = True
                    
            
            #define the conceptual model
            if self.config['recession']['hydrogeo_parameter_estimation']['rorabaugh_simplification']:
                if self.config['recession']['fitting']['recession_algorithm'].lower() != 'maillet':
                    raise ValueError('Rorabaugh method requires maillet based recession (exponential model), please change set up')
                else:
                    conceptual_model = 'rorabaugh'
            else:                    
                conceptual_model=self.config['recession']['fitting'][
                'recession_algorithm']
            
            logger.info(f'Hydrogeo Parameters will be infered based on the model of {conceptual_model}')
                
                    
                    


            network_geometry = gpd.read_file(Path(self.paths["input_dir"],
                                                  self.config['file_io']['input']['geospatial'][
                                                      'river_network'])
                                             )
            #write lower case
            network_geometry['reach_name'] = network_geometry['reach_name'].apply(lambda x: x.lower())
            # get the properties
            
            self.gauges_meta, self.hydrogeo_parameter_names = get_hydrogeo_properties(gauge_data=self.gauges_meta,
                                                              basins = basins,
                                                              basin_id_col =self.config['waterbalance'][
                                                                  'basin_id_col'],
                                                              gw_surface = gw_surface,
                                                              network=network_geometry,
                                                              conceptual_model=conceptual_model,
                                                              )
        
        if self.output:
            #the meta data
            self.gauges_meta.to_csv(Path(self.paths["output_dir"], 'data', 'gauges_meta.csv'))
            #the result of the recession
            self.master_recession_curves.to_csv(Path(self.paths["output_dir"], 'data', 'master_recession_curves.csv'))
            self.recession_limbs_ts.to_csv(Path(self.paths["output_dir"], 'data', 'recession_limbs_time_series.csv'))


    def get_water_balance(self, **kwargs):
        """Calculate water balance per section"""
        
        logger.info('We analyse the Water Balance per Section')
        
        # check whether network data is available
        if self.config['file_io']['input']['geospatial']['river_network'] is None:
            logger.warning('No Geofile for stream network data provided, water balance wont be calculated')
            return

        # %% First we load the data
        self.gauges_meta.index.name = 'gauge'
        network_geometry = gpd.read_file(Path(self.paths["input_dir"],       
                                              self.config['file_io']['input']['geospatial']['river_network'])
                                         )

        network_geometry['reach_name'] = network_geometry['reach_name'].apply(lambda x: x.lower())
        
        if self.config['file_io']['input']['geospatial']['branches_topology'] is None:
            network_connections = pd.DataFrame(columns=['index',
                                                        'stream',
                                                        'main_stream',
                                                        'type',
                                                        'distance_junction_from_receiving_water_mouth'
                                                        ])
        else:
            network_connections = pd.read_csv(Path(self.paths["input_dir"],
                                                   self.config['file_io']['input']['geospatial'][
                                                       'branches_topology'])
                                              )
            
        #also write to lower case
        for col in ['stream','main_stream']:
            network_connections[col] = network_connections[col].apply(lambda x: x.lower())
        #add basin data
        if self.config['file_io']['input']['geospatial']['gauge_basins'] is not None:
            gauge_basins = gpd.read_file(Path(self.paths["input_dir"],
                                              self.config['file_io']['input']['geospatial']['gauge_basins'])
                                         )
            gauge_basins[self.config['waterbalance']['basin_id_col']] = gauge_basins[self.config['waterbalance']['basin_id_col']].apply(lambda x: x.lower())
            #rewrite to lower case
            gauge_basins[self.config['waterbalance']['basin_id_col']] = gauge_basins[self.config['waterbalance']['basin_id_col']].apply(lambda x: x.lower())
            # check whether flow type is given explicitely
        else:
            gauge_basins=None
            logger.info('No GIS Data for gauged basin geometry provided')

        if 'flow_type' in kwargs:
            flow_type = kwargs['flow_type']
        else:
            flow_type = self.config['waterbalance']['flow_type']
            
        #if baseflow we activate the baseflow control
        #if flow_type == 'baseflow':
            #self.config['baseflow']['activate'] = True
            
        #%%process the flow data
        if self.config['waterbalance']['bayesian_updating']['activate']:
            logger.info('Generate discharge from discharge with uncertainty')
            # Generate uncertainty
            gauge_uncertainty = uncertainty_data_generation(self.gauges_meta, 
                                                             self.gauge_ts, 
                                                             self.config['waterbalance']['bayesian_updating'],
                                                             )
            gauge_uncertainty.add_uncertainty()
            self.data_ts_uncertain = gauge_uncertainty.generate_samples().set_index('date')
            
            if flow_type == 'baseflow':
                logger.info('Use baseflow time series')           
                balance_value_var = 'BF'
                
                self.get_baseflow(data_ts=self.data_ts_uncertain,data_var='Q*')
                    
                
        
                
                # prove whether explicitely daily values should be calculate otherwise we take monthly
                if self.config['waterbalance']['time_series_analysis_option'] == 'daily' and 'bf_' + \
                        self.config['waterbalance']['time_series_analysis_option'] in self.bf_output.keys():
                    self.q_parameter ='bf_daily'
                    self.data_ts_uncertain = self.bf_output[self.q_parameter].copy()
                else:
                    logger.info('Monthly Averaged values are used')
                    self.q_parameter ='bf_monthly'
                    self.data_ts_uncertain = self.bf_output[self.q_parameter].copy()
            
            else:
                balance_value_var = 'Q*'
                self.q_parameter ='q_daily'
                logger.info('For Discharge with uncertainty we just need to adapt the time')
                if self.config['waterbalance']['time_series_analysis_option'] =='monthly':
                    self.q_parameter ='q_monthly'
                    self.data_ts_uncertain = self.data_ts_uncertain.groupby(['gauge','sample_id']).resample('m').mean(numeric_only=True).drop(columns='sample_id')
                    self.data_ts_uncertain['bf_method'] = 'discharge'

            #copy back
            data_ts = self.data_ts_uncertain.copy()
            
        else:
            logger.info('Calculate water balance without uncertainty incooporation')
            data_value_var_name = 'Q'
            data_ts=self.gauge_ts.reset_index().melt(id_vars='date',value_name=data_value_var_name).set_index('date')
            data_ts.rename(columns={'variable':'gauge'},inplace=True)
            data_ts['sample_id'] = 0
            balance_value_var = data_value_var_name
            
            if flow_type == 'baseflow': 
                balance_value_var = 'BF'
                logger.info('Use baseflow time series')
                # check whether the baseflow as already be computed
                if not self.bf_output:
                    logger.info('Calculate Baseflow first before baseflow water balance can be calculated')
                    self.get_baseflow(data_ts=data_ts,
                                      data_var=data_value_var_name)
                
                # prove whether explicitely daily values should be calculate otherwise we take monthly
                if self.config['waterbalance']['time_series_analysis_option'] == 'daily' and 'bf_' + \
                        self.config['waterbalance']['time_series_analysis_option'] in self.bf_output.keys():
                    data_ts = self.bf_output['bf_daily'].copy()
                else:
                    logger.info('Monthly Averaged values are used')
                    data_ts = self.bf_output['bf_monthly'].copy()


            elif flow_type == 'discharge':
                logger.info('Use daily discharge')
                data_ts['bf_method'] = 'discharge'

        # start the calculation
        #ignore the statistics depending on the baseflow method
        logger.info('Current Implementation takes the average of different bf_methods for calculation of water balance')
        drop_index=False
        data_ts = data_ts.reset_index(drop=drop_index).groupby(['sample_id','gauge','date']).mean(numeric_only=True).reset_index().set_index('date')
        
        #calculate water balance
        self.sections_meta, self.q_diff, self.network_map, self.section_basin_map,ts_stats = get_section_waterbalance(
            gauge_data=self.gauges_meta,
            data_ts=data_ts,
            stream_network=network_geometry,
            basins=gauge_basins,
            network_connections=network_connections,
            confidence_acceptance_level=self.config['waterbalance']['confidence_acceptance_level'],
            time_series_analysis_option=self.config['waterbalance']['time_series_analysis_option'],
            basin_id_col=self.config['waterbalance']['basin_id_col'],
            decadal_stats = self.config['time']['compute_each_decade'],
            bayesian_options=self.config['waterbalance']['bayesian_updating'],
            balance_col_name = balance_value_var,
        )
        
        #we map the mean_balance information on the geodataframes
        balance_mean = self.sections_meta.groupby(['downstream_point','decade']).mean(numeric_only=True).loc[:,'balance[m³/s]']
        
        #reorganize self_gauges_meta and add gauges_mean
        self.gauges_meta = self.gauges_meta.reset_index().set_index(['gauge','decade'])
        balance_mean.index.names = self.gauges_meta.index.names        
        self.gauges_meta = pd.merge(self.gauges_meta.reset_index(),
                                    balance_mean.reset_index(),
                                    how='left',
                                    on=['gauge','decade'])
        self.gauges_meta=self.gauges_meta.set_index(['gauge', 'decade'])


        # map results of analysis to geodataframes
        logger.info('Map statistics on stream network geodata')
        self.network_map=map_time_dependent_cols_to_gdf(self.network_map,
                                                            self.gauges_meta,
                                                            geodf_index_col='downstream_point',
                                                            time_dep_df_index_col ='gauge',
                                                            time_dep_df_time_col = 'decade',
                                                            )
        if self.section_basin_map is not None:
            logger.info('Map statistics on subbasin geodata')
            self.section_basin_map=map_time_dependent_cols_to_gdf(self.section_basin_map, 
                                                               self.gauges_meta.drop(columns='basin_area'),
                                                               geodf_index_col='basin',
                                                                time_dep_df_index_col ='gauge',
                                                                time_dep_df_time_col = 'decade',
                                                                )           
  
        if self.output:
            self.sections_meta.to_csv(Path(self.paths["output_dir"], 'data', 'sections_meta.csv'))
            self.q_diff.to_csv(Path(self.paths["output_dir"], 'data', 'q_diff.csv'))
            self.network_map.to_file(Path(self.paths["output_dir"], 'data', 'sections_streamlines.gpkg'),
                                         driver='GPKG')
            
            if self.section_basin_map is not None:
                self.section_basin_map.to_file(Path(self.paths["output_dir"], 'data', 'sections_subbasin.gpkg'), driver='GPKG')
            #the gauge meta data
            self.gauges_meta.to_csv(Path(self.paths["output_dir"], 'data', 'gauges_meta.csv'))
            gdf_gauge_meta = gpd.GeoDataFrame(data=self.gauges_meta,
                                            geometry=[Point(xy) for xy in zip(self.gauges_meta.easting, self.gauges_meta.northing)],
                                            crs=self.network_map.crs,
                            )
            gdf_gauge_meta.to_file(Path(self.paths["output_dir"], 'data', 'gauges_meta.gpkg'), driver='GPKG')


def main(config_file=None, output=True):
    if config_file:
        configuration = Model.read_config(config_file)
    else:
        configuration = Model.read_config(Path(Path(__file__).parents[1], "data/examples/sbat.yml"))

    sbat = Model(configuration, output)
    # get discharge data
    logger.info(f'discharge statistics activation is set to {sbat.config["discharge"]["activate"]}')
    if sbat.config['discharge']['activate']:
        sbat.get_discharge_stats()
        
    
    # get baseflow        
    logger.info(f'baseflow computation activation is set to {sbat.config["baseflow"]["activate"]}')
    if sbat.config['baseflow']['activate']:
        
        
        sbat.get_baseflow(data_ts=sbat.gauge_ts)
        
    # do the recession analysis
    logger.info(f'recession computation activation is set to {sbat.config["recession"]["activate"]}')
    if sbat.config['recession']['activate']:
        sbat.get_recession_curve()
        
    
    # water balance
    logger.info(f'water balance computation activation is set to {sbat.config["recession"]["activate"]}')
    if not hasattr(sbat, 'section_meta') and sbat.config['waterbalance']['activate'] :
        sbat.get_water_balance()
        
    # the plotting
    if sbat.config['file_io']['output']['plot_results']:
        Plotter(sbat)

    logging.shutdown()
    return sbat



if __name__ == "__main__":


    if sys.argv == 1:
        cfg_file = sys.argv.pop(1)
        main(config_file=cfg_file)
    else:
        main()
    logging.shutdown()
